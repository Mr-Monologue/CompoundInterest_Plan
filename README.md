# SmartInvest - 智能定投系统

一个基于网格策略的智能定投系统，支持基金、ETF 等资产的自动化投资建议和交易记录管理。

## 📋 项目简介

SmartInvest 是一个全栈投资管理系统，通过分析市场数据（价格、MA200、波动率等），基于网格策略自动生成投资建议。系统支持多资产管理、交易记录、策略回测和组合调度等功能。

### 核心特性

- 🎯 **智能策略引擎**：基于 Z-Score 和网格位置的动态定投策略
- 📊 **实时行情获取**：支持场外基金、ETF、股票等多数据源
- 💰 **全局资金管理**：周预算 + 全局准备金池的智能分配
- 📈 **可视化看板**：实时展示价格走势、MA200、投资建议等
- 📝 **交易记录管理**：完整的买卖记录和持仓统计
- 🔄 **组合调度**：一键执行全组合策略，按低估程度自动分配资金
- 📑 **策略复盘**：生成周报和历史分析报告

## 🛠️ 技术栈

### 后端
- **FastAPI** - 现代 Python Web 框架
- **SQLModel** - 基于 SQLAlchemy 和 Pydantic 的 ORM
- **SQLite** - 轻量级数据库
- **AKShare / yfinance** - 金融数据获取
- **Pandas / NumPy** - 数据处理和计算

### 前端
- **React 19** - UI 框架
- **TypeScript** - 类型安全
- **Vite** - 构建工具
- **Recharts** - 数据可视化
- **Lucide React** - 图标库

## 📁 项目结构

```
SmartInvest/
├── backend/                 # 后端服务
│   ├── db/                 # 数据库相关
│   │   ├── database.py     # 数据库连接和初始化
│   │   ├── models.py       # 数据模型定义
│   │   └── state.py        # 全局状态管理
│   ├── services/           # 业务逻辑层
│   │   ├── market.py       # 市场数据获取（多数据源）
│   │   ├── strategy.py     # 策略计算引擎
│   │   └── portfolio.py   # 组合调度逻辑
│   ├── main.py            # FastAPI 应用入口
│   └── invest.db          # SQLite 数据库文件
│
└── frontend/              # 前端应用
    ├── src/
    │   ├── App.tsx        # 主应用组件
    │   ├── App.css        # 样式文件
    │   └── main.tsx       # 入口文件
    ├── package.json       # 依赖配置
    └── vite.config.ts     # Vite 配置
```

## 🚀 快速开始

### 环境要求

- Python 3.8+
- Node.js 16+
- npm 或 yarn

### 后端安装与运行

1. **进入后端目录**
```bash
cd backend
```

2. **创建虚拟环境（推荐）**
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

3. **安装依赖**
```bash
pip install fastapi uvicorn sqlmodel pandas numpy akshare yfinance requests
```

4. **运行后端服务**
```bash
python main.py
```

后端服务将在 `http://127.0.0.1:8000` 启动

### 前端安装与运行

1. **进入前端目录**
```bash
cd frontend
```

2. **安装依赖**
```bash
npm install
```

3. **启动开发服务器**
```bash
npm run dev
```

前端应用将在 `http://localhost:5173` 启动（Vite 默认端口）

## 📡 API 文档

### 资产管理

- `GET /api/assets` - 获取所有资产列表
- `POST /api/assets` - 添加新资产
  ```json
  {
    "code": "005827",
    "name": "易方达蓝筹精选"
  }
  ```
- `DELETE /api/assets/{asset_id}` - 删除资产

### 行情与建议

- `GET /api/advice/{code}` - 获取实时投资建议
  - 返回：当前价格、MA200、网格位置、建议金额、操作建议等

### 交易记录

- `POST /api/transactions` - 记录交易
  ```json
  {
    "asset_code": "005827",
    "type": "BUY",
    "price": 1.9775,
    "amount": 200.0,
    "date": "2025-11-28"
  }
  ```
- `GET /api/portfolio/{code}` - 获取持仓统计

### 策略执行

- `POST /api/strategy/run/{code}` - 执行单个标的策略分析
- `GET /api/strategy/report/{code}?days=7` - 获取策略复盘报告

### 全局计划

- `GET /api/plan/state` - 获取全局状态（周预算、准备金等）
- `POST /api/plan/run` - 一键执行全组合策略

## 💡 使用说明

### 1. 添加资产

在侧边栏点击"添加标的"按钮，输入基金代码（如 `005827`）和名称，系统会自动获取行情数据。

### 2. 查看投资建议

点击侧边栏中的资产，系统会：
- 获取实时价格和 MA200
- 计算网格位置（Z-Score）
- 生成投资建议（买入/等待/卖出）
- 显示历史价格走势图

### 3. 记录交易

在资产详情页点击"记账"按钮，输入交易信息（价格、金额、类型），系统会自动计算份额并记录。

### 4. 执行策略

- **单标策略**：在资产详情页点击"执行策略"，系统会计算今日建议并保存到数据库
- **全组合策略**：点击"执行全组合"，系统会：
  1. 遍历所有资产，计算网格位置
  2. 按低估程度排序
  3. 自动分配周预算和准备金
  4. 生成交易记录

### 5. 查看复盘报告

在资产详情页的"策略复盘"卡片中，可以查看最近 N 天的策略执行历史。

## 🧠 策略说明

### 网格策略算法

系统使用基于 Z-Score 的网格策略：

1. **网格位置计算**
   - 网格宽度 = 波动率 × 0.6（最小 0.5%）
   - 网格位置 = (当前价格 - MA200) / MA200 / 网格宽度

2. **估值区间**
   - **低估区** (Grid < -1.0)：几何加码，动用准备金
   - **合理区** (-1.0 ≤ Grid ≤ 2.0)：正常定投
   - **高估区** (Grid > 2.0)：停止买入，存入准备金

3. **资金分配**
   - 基础金额：200 元/周
   - 动态加码：根据网格位置几何递增（最大 5 倍）
   - 准备金机制：高估时存入，低估时取出

### 数据源优先级

**场外基金**（如 005827）：
1. 东方财富 `pingzhongdata` JS 接口（直连 → VPN）
2. 东方财富 `lsjz` 接口（直连 → VPN）
3. 腾讯财经接口（备用）

**ETF/股票**（如 sh000300）：
1. 东方财富 ETF 接口
2. Yahoo Finance（备用）

## 🗄️ 数据库模型

### Asset（资产表）
- `id`: 主键
- `code`: 资产代码（唯一）
- `name`: 资产名称
- `type`: 资产类型

### Transaction（交易表）
- `id`: 主键
- `asset_code`: 资产代码
- `date`: 交易日期
- `type`: 交易类型（BUY/SELL）
- `price`: 成交价
- `amount`: 成交金额
- `units`: 成交份额

### FundState（基金状态表）
- `id`: 主键
- `asset_code`: 资产代码（唯一）
- `cumulative_reserve_usage`: 累计准备金使用量
- `last_signal_date`: 最后信号日期

### DailyPlan（每日计划表）
- `id`: 主键
- `asset_code`: 资产代码
- `date`: 日期
- `close`: 收盘价
- `ma200`: MA200 值
- `dev_pct`: 偏离度
- `level`: 估值等级
- `base_amt`: 基础金额
- `dyn_amt`: 动态金额
- `total_amt`: 总金额
- `reserve_before/after`: 准备金快照

### PlanState（全局计划表）
- `id`: 固定为 1
- `weekly_budget`: 周预算（默认 200）
- `global_reserve`: 全局准备金
- `current_week_start`: 本周起始日
- `budget_used_this_week`: 本周已用预算

## 🔧 开发说明

### 代码规范

- 后端：遵循 PEP 8，使用类型提示
- 前端：使用 TypeScript，遵循 React Hooks 最佳实践
- 数据库操作：使用 SQLModel，通过 Session 管理

### 添加新功能

1. **添加新的数据源**：在 `backend/services/market.py` 中添加新的 `fetch_*` 函数
2. **修改策略逻辑**：编辑 `backend/services/strategy.py` 中的 `calculate_grid_logic`
3. **添加新的 API**：在 `backend/main.py` 中添加路由
4. **前端组件**：在 `frontend/src/App.tsx` 中添加新的 UI 组件

### 调试技巧

- 后端日志：SQLModel 的 `echo=True` 会打印所有 SQL 语句
- 前端调试：使用浏览器开发者工具查看网络请求
- 数据库查看：可以使用 SQLite 工具（如 DB Browser）查看 `invest.db`

## ⚠️ 注意事项

1. **数据源稳定性**：部分数据源可能需要 VPN 或代理，系统已实现自动降级
2. **缓存机制**：市场数据缓存 10 分钟，避免频繁请求
3. **数据库备份**：建议定期备份 `invest.db` 文件
4. **周预算重置**：系统会在检测到新的一周时自动重置周预算

## 📝 更新日志

### v2.0
- ✅ 重构策略引擎，使用全局准备金池
- ✅ 添加组合调度功能
- ✅ 优化数据获取，支持多数据源降级
- ✅ 添加策略复盘报告
- ✅ 前端 UI 优化，支持删除资产

### v1.0
- ✅ 基础资产管理
- ✅ 实时行情获取
- ✅ 网格策略计算
- ✅ 交易记录管理

## 📄 许可证

本项目仅供学习和研究使用。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

**提示**：投资有风险，本系统仅供参考，不构成投资建议。请根据自身情况谨慎投资。

