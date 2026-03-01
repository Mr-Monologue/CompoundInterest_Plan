# SmartInvest — 智能定投系统 v2.0

基于网格策略的自主定投系统，纯后端架构，适配 RK3588 / clawbot 部署。

## 架构

```
SmartInvest/
├── backend/
│   ├── main.py                 # FastAPI 入口 + 全部 API 路由
│   ├── scheduler.py            # APScheduler 自主调度器
│   ├── db/
│   │   ├── database.py         # SQLite 引擎 + 建表
│   │   ├── models.py           # SQLModel 数据模型
│   │   └── state.py            # 全局状态管理
│   └── services/
│       ├── market.py           # 行情获取（东财/腾讯/Yahoo 多源回退）
│       ├── strategy.py         # 网格策略引擎
│       ├── portfolio.py        # 组合调度 + 双重刹车
│       └── holdings.py         # 基金持仓穿透
├── deploy/
│   └── smartinvest.service     # systemd 服务文件
├── requirements.txt
└── start.sh                    # Linux 启动脚本
```

## 核心策略

### 网格定投 v2.1

以 MA200 为锚，用波动率自适应网格宽度：

| 区间 | 网格位置 | 动作 |
|------|----------|------|
| 高估 | ≥ +2 格 | 暂停定投，全额蓄力 |
| 中高 | 0 ~ +2 格 | 线性收缩投入（100% → 0%） |
| 中低 | -2 ~ 0 格 | 标准定投（100%） |
| 低估 | ≤ -2 格 | 几何加码（1.5×1.2^n，最大5倍） |

### 双重刹车

- **单标的仓位上限**：默认 20%，接近时线性减速
- **行业穿透限额**：默认 30%，通过基金持仓穿透计算

### 自主调度

| 任务 | 频率 | 说明 |
|------|------|------|
| 每日策略执行 | 工作日 15:30 | A股收盘后自动运行全组合策略 |
| 每周自动充值 | 周一 09:00 | 按配置金额向资金池注资 |
| 持仓数据同步 | 周日 02:00 | 更新全部基金持仓和行业数据 |

## 快速开始

### 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 启动服务

```bash
./start.sh
```

服务启动后：
- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/health

### RK3588 部署

```bash
# 1. 拷贝项目到目标设备
scp -r . clawbot@<IP>:/opt/smartinvest/

# 2. 安装 systemd 服务
sudo cp deploy/smartinvest.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable smartinvest
sudo systemctl start smartinvest

# 3. 查看运行状态
sudo systemctl status smartinvest
journalctl -u smartinvest -f
```

## API 概览

### 资产管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/assets` | 列出所有资产 |
| POST | `/api/assets` | 添加资产 |
| DELETE | `/api/assets/{id}` | 删除资产 |

### 行情与策略
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/advice/{code}` | 获取实时建议 |
| POST | `/api/strategy/run/{code}` | 执行单标的策略 |
| GET | `/api/strategy/report/{code}` | 策略复盘报告 |
| POST | `/api/plan/run` | 一键执行全组合策略 |

### 资金池
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/pool` | 资金池状态 |
| POST | `/api/pool/deposit` | 充值 |
| POST | `/api/pool/config` | 配置更新 |

### 调度与运维
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/system/status` | 系统总览 |
| GET | `/api/scheduler/jobs` | 查看定时任务 |
| POST | `/api/scheduler/trigger/{job_id}` | 手动触发任务 |
| POST | `/api/scheduler/pause/{job_id}` | 暂停任务 |
| POST | `/api/scheduler/resume/{job_id}` | 恢复任务 |
