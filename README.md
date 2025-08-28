# 智能定投系统

一个基于Streamlit的投资仪表盘应用，采用标准Python项目布局和模块化设计，提供动态定投建议、持仓分析和估值监控功能。

## 🏗️ 项目结构

```
CompoundInterestPlan/
├─ requirements.txt              # 依赖管理
├─ README.md
├─ run_gui.py                   # 主启动脚本
├─ data/
│  ├─ config.json               # 多基金配置
│  └─ trend.db                  # SQLite 数据库
└─ src/
   └─ app/
      ├─ ui/
      │  └─ gui.py              # Streamlit GUI 入口
      ├─ services/
      │  └─ actions.py          # GUI 调用的一次性动作（采样并保存）
      ├─ core/
      │  ├─ config.py           # 读取/合并 config.json
      │  ├─ data_sources.py     # 抓净值/指数（带回退）
      │  ├─ signals.py          # 偏离度 & 定投建议（平滑）
      │  └─ holdings.py         # 持仓精算（Decimal）
      └─ db/
         └─ storage.py          # SQLite v2 表封装（全带 fund_code）
```

### 模块化架构

1. **core/config.py** - 配置管理
   - 默认参数定义
   - 用户自定义JSON读取
   - 配置验证

2. **core/data_sources.py** - 数据源管理
   - AKShare/yfinance/天天基金数据抓取
   - @st.cache_data 缓存机制
   - 网络失败回退策略

3. **core/signals.py** - 信号计算
   - MA200 偏离计算
   - 阈值/平滑映射
   - 动态定投比例计算

4. **core/holdings.py** - 持仓计算
   - Decimal 精度运算
   - 持有/累计盈亏计算
   - 盈亏平衡净值计算

5. **db/storage.py** - 数据存储
   - SQLite v2 表封装
   - 全带 fund_code 支持多基金
   - 数据迁移和版本管理

6. **services/actions.py** - 服务层
   - 每日任务执行
   - GUI 按钮触发的操作
   - 数据采样并保存

### 页面结构

- **📊 总览**: 多基金状态总览
- **🔍 基金详情**: 单个基金的详细分析
- **📈 持仓**: 持仓管理和盈亏分析
- **📅 周复盘**: 最近一周的定投记录

## 🚀 快速开始

### 1. 环境准备

#### 创建虚拟环境（推荐）
```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1  # Windows PowerShell
# 或
source .venv/bin/activate     # Linux/Mac
```

#### 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 配置基金信息

编辑 `data/config.json` 文件，设置您的基金配置：

```json
{
  "defaults": {
    "weekly_budget": 200.0,
    "fixed_ratio": 0.40,
    "reserve_cap_months": 3,
    "max_weekly_multiple": 3.0,
    "ma200_low": -10.0,
    "ma200_mid": 5.0,
    "alloc_low": 0.75,
    "alloc_mid": 0.25,
    "alloc_high": 0.0
  },
  "funds": [
    {
      "fund_code": "000083",
      "fund_name": "汇添富消费行业混合",
      "fund_name_en": "000083.SZ",
      "proxy_index": "000932",
      "proxy_index_en": "000932.SS",
      "weekly_budget": 200.0,
      "manual_holdings": {
        "enabled": true,
        "units_left": 6.63,
        "avg_cost": 6.8627,
        "realized_pnl": -7.24
      }
    }
  ]
}
```

### 3. 启动应用

#### 方式一：使用主启动脚本（推荐）
```bash
python run_gui.py
```

#### 方式二：直接运行 Streamlit
```bash
streamlit run src/app/ui/gui.py
```

应用将在浏览器中自动打开，默认地址：http://localhost:8501

### 4. 基金管理

系统支持多基金配置管理，您可以通过 GUI 进行以下操作：

#### 添加新基金
1. 在侧边栏点击 "➕ 添加基金" 展开表单
2. 填写基金信息：
   - 基金代码（如：000083）
   - 基金名称（如：汇添富消费行业混合）
   - yfinance代码（如：000083.SZ）
   - 代理指数（如：000932）
   - 代理指数_en（如：000932.SS）
   - 每周预算金额
3. 点击 "保存到配置" 按钮

#### 数据采样
1. 在侧边栏选择要操作的基金
2. 点击 "📥 采样并保存（估值+建议）" 按钮
3. 系统将自动获取最新数据并计算定投建议

#### 持仓管理
1. 切换到 "📈 持仓" 标签页
2. 在 "手动持仓" 表单中更新持仓信息
3. 点击 "保存" 更新配置

## 📊 功能特性

### 动态定投策略
- 基于MA200偏离度的智能定投
- 平滑映射避免阈值跳跃
- 准备金管理机制
- 多基金独立管理

### 数据源管理
- 多数据源支持（AKShare、yfinance）
- 智能回退策略
- 缓存机制提升性能
- 实时数据更新

### 持仓分析
- Decimal精度计算
- 实时盈亏分析
- ROI指标计算
- 持仓快照记录

### 交互式界面
- Streamlit现代化界面
- 多标签页组织
- 实时数据刷新
- 响应式设计

## ⚙️ 配置说明

### 主要参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `weekly_budget` | 周定投预算 | 200.0 |
| `fixed_ratio` | 固定定投比例 | 0.40 |
| `reserve_cap_months` | 准备金上限月数 | 3 |
| `max_weekly_multiple` | 最大周倍数 | 3.0 |
| `ma200_low` | 低估阈值 | -10.0% |
| `ma200_mid` | 中估阈值 | 5.0% |
| `alloc_low` | 低估时分配比例 | 0.75 |
| `alloc_mid` | 中估时分配比例 | 0.25 |
| `alloc_high` | 高估时分配比例 | 0.0 |

### 数据库表结构

- **nav_daily_v2**: 基金净值历史
- **proxy_daily_v2**: 代理指数数据
- **dca_plan_v2**: 定投计划记录
- **holdings_snapshot_v2**: 持仓快照
- **fund_state**: 基金状态管理

## 🔧 开发说明

### 环境要求
- Python 3.8+
- Streamlit 1.49+
- 建议使用虚拟环境

### 核心依赖
- `streamlit` - Web界面框架
- `pandas` - 数据处理
- `numpy` - 数值计算
- `akshare` - 中国金融数据
- `yfinance` - 全球金融数据
- `requests-cache` - 请求缓存
- `plotly` - 交互式图表

### 模块测试

每个模块都可以独立测试：

```bash
python -c "from src.app.core.config import load_all_funds_config; print(load_all_funds_config())"
python -c "from src.app.core.data_sources import get_latest_nav_with_fallback; print('Data sources OK')"
```

### 添加新功能

1. 在相应模块中添加函数
2. 在 `src/app/ui/gui.py` 中集成到页面
3. 更新配置和文档

## 📈 使用建议

### 定投策略
- 根据个人风险承受能力调整阈值
- 定期检查准备金余额
- 关注MA200趋势变化
- 合理分配多基金投资

### 数据更新
- 净值数据实时更新
- 指数数据实时更新
- 可手动清除缓存强制更新
- 建议每日进行数据采样

### 风险提示
- 本工具仅供参考，不构成投资建议
- 投资有风险，入市需谨慎
- 请根据个人情况调整投资策略
- 定期评估和调整投资组合

## 🤝 贡献指南

欢迎提交Issue和Pull Request！

### 开发环境设置
```bash
# 克隆项目
git clone <repository-url>
cd CompoundInterestPlan

# 创建虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 安装依赖
pip install -r requirements.txt

# 启动开发服务器
python run_gui.py
```

### 代码规范
- 遵循PEP 8规范
- 添加类型注解
- 编写文档字符串
- 保持模块化设计

## 📄 许可证

MIT License

## 📞 联系方式

如有问题或建议，请通过GitHub Issues联系。