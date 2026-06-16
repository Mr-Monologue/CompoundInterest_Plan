#!/usr/bin/env python3
"""
Hermes Watcher — 本地常驻守护进程

不直接写 SQLite，不创建交易，不修改代码。
只调用 FastAPI 统一入口，生成 reports / alerts 文件。

启动: python scripts/hermes_watcher.py
安全停止: Ctrl+C
"""

import os
import sys
import json
import time
import signal
import threading
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any

# ── 配置（从 .env 读取）───────────────────────────────

def _load_dotenv():
    """简易 .env 加载器（不依赖 python-dotenv）"""
    env_path = Path("data/.env")
    if not env_path.exists():
        env_path = Path(".env")
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k not in os.environ:
                    os.environ[k] = v

_load_dotenv()

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8701")
LOCAL_API_TOKEN = os.getenv("CIP_API_TOKEN", "local-dev-token-change-me")

DAILY_TIME = os.getenv("HERMES_WATCHER_DAILY_TIME", "18:00")
ANOMALY_TIME = os.getenv("HERMES_WATCHER_ANOMALY_TIME", "18:10")
WEEKLY_DAY = os.getenv("HERMES_WATCHER_WEEKLY_DAY", "FRI").upper()
WEEKLY_TIME = os.getenv("HERMES_WATCHER_WEEKLY_TIME", "18:20")
AUTO_CATCHUP = os.getenv("HERMES_WATCHER_AUTO_CATCHUP", "false").lower() in ("true", "1", "yes")

# 路径
REPORTS_DIR = Path("reports")
DAILY_DIR = REPORTS_DIR / "daily"
WEEKLY_DIR = REPORTS_DIR / "weekly"
ALERTS_DIR = Path("alerts")

# 星期映射
WEEKDAYS = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}

running = True


def ensure_dirs():
    for d in [DAILY_DIR, WEEKLY_DIR, ALERTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


# ── HTTP 客户端（stdlib）──────────────────────────────

def _request(method: str, path: str, body: dict = None, timeout: int = 30) -> Dict[str, Any]:
    """发送 HTTP 请求到 API，返回 JSON"""
    url = f"{API_BASE}{path}"
    data = None
    headers = {"X-Local-Token": LOCAL_API_TOKEN, "Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    elif method == "GET":
        headers.pop("Content-Type", None)

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {e.code}", "detail": err_body[:500]}
    except Exception as e:
        return {"error": str(e)}


def _post(path: str, body: dict) -> dict:
    return _request("POST", path, body)


def _get(path: str) -> dict:
    return _request("GET", path)


# ── 日志 ─────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ── 目录确保 ─────────────────────────────────────────

def _write_md(filepath: Path, content: str):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")
    log(f"  📄 写入: {filepath}")


# ── API 健康检查 ─────────────────────────────────────

def check_api_health() -> bool:
    """检查 API 是否可用"""
    try:
        r = _get("/api/health")
        if r.get("status") == "ok":
            log(f"✅ API 可用: v{r.get('version','?')}")
            return True
    except Exception:
        pass
    log(f"❌ API 不可用: {API_BASE}")
    log(f"   请先启动: python -m src.app.api --port 8701")
    return False


# ── 检查当天是否已有采样 ─────────────────────────────

def check_today_sampled() -> bool:
    today = date.today().isoformat()
    r = _get("/api/plan/latest?fund_code=000083")
    plan_date = r.get("date", "")
    if plan_date == today:
        return True
    log(f"⚠️ 今天 ({today}) 尚未采样（最新计划日期: {plan_date}）。")
    if AUTO_CATCHUP:
        log("   AUTO_CATCHUP=true，将执行自动补写...")
        return False
    else:
        log("   可手动执行: python -m src.app.services.actions --dry-run")
        return False  # 不自动触发，但返回 False 供调用方判断


# ── 每日采样任务 ─────────────────────────────────────

def run_daily_sample():
    today = date.today().isoformat()
    log(f"📥 执行每日采样...")
    r = _post("/api/snapshot/daily/run", {"created_by": "scheduler"})

    if "error" in r:
        log(f"❌ 采样失败: {r['error']}")
        _write_alerts("API_ERROR", f"采样 API 调用失败: {r.get('error')}")
        return

    results = r.get("results", [])
    lines = [f"# 每日定投采样 — {today}", "", f"生成时间: {datetime.now().isoformat()}", ""]

    any_blocked = False
    for item in results:
        code = item.get("fund_code", "?")
        action = item.get("action_allowed", False)
        rec = item.get("recommended_amount")
        trace = item.get("calculation_trace", {})
        source = item.get("data_source", "?")
        dev = item.get("dev_pct", 0)
        nav = item.get("fund_nav", 0)

        lines.append(f"## {code}")
        lines.append(f"- 净值: {nav:.4f}")
        lines.append(f"- MA200 偏离: {dev*100:.2f}%")
        lines.append(f"- 数据源: {source}")
        lines.append(f"- risk_guard: {'PASS' if action else 'FAIL'}")
        lines.append(f"- 建议金额: ¥{rec:.2f}" if rec is not None else "- 建议金额: null (BLOCKED)")
        lines.append(f"- 准备金余额: ¥{trace.get('reserve_after', 0):.2f}")
        lines.append("")

        if not action:
            any_blocked = True

    _write_md(DAILY_DIR / f"{today}.md", "\n".join(lines))

    if any_blocked:
        blocked_lines = [f"# ⛔ BLOCKED — {today}", "",
                         "以下基金因风险防护未通过，未生成建议金额：", ""]
        for item in results:
            if not item.get("action_allowed", False):
                code = item.get("fund_code", "?")
                errors = item.get("risk_guard_errors", [])
                blocked_lines.append(f"- **{code}**: {'; '.join(errors) if errors else '原因未知'}")
        blocked_lines.append("")
        blocked_lines.append("> 系统已自动阻断。请人工复核后决定是否手动操作。")
        _write_md(ALERTS_DIR / f"{today}_BLOCKED.md", "\n".join(blocked_lines))
        log("⛔ BLOCKED — 数据异常，需要人工复核")
    else:
        log("✅ PASS — 采样完成，可人工复核")


# ── 异常检查任务 ─────────────────────────────────────

def run_anomaly_check():
    today = date.today().isoformat()
    log(f"🔍 执行异常检查...")

    anomalies = []
    r = _get("/api/plan/latest?fund_code=000083")

    if "error" in r:
        anomalies.append(f"- API 错误: {r.get('error')}")
    else:
        dev_pct = r.get("dev_pct", 0)
        nav_data = _get("/api/snapshot/latest?fund_code=000083")
        nav = nav_data.get("nav", 0)
        source = nav_data.get("proxy_source", nav_data.get("nav_source", "?"))

        if source and source.lower() == "mock":
            anomalies.append(f"- source=Mock（不可信）")
        if not r.get("action_allowed", True):
            anomalies.append(f"- action_allowed=false")
        if r.get("recommended_amount") is not None and not r.get("action_allowed", True):
            anomalies.append(f"- ⚠️ BLOCKED 状态下 recommended_amount 非 null")
        if nav is not None and (nav <= 0 or nav > 20):
            anomalies.append(f"- NAV 异常: {nav}")
        if dev_pct is not None and abs(dev_pct) > 0.5:
            anomalies.append(f"- dev_pct 异常: {dev_pct*100:.2f}%")
        data_date = r.get("date", "")
        if data_date:
            try:
                dd = datetime.strptime(data_date, "%Y-%m-%d").date()
                if (date.today() - dd).days > 3:
                    anomalies.append(f"- 数据过旧: {data_date}（{ (date.today()-dd).days } 天前）")
            except ValueError:
                pass

    if anomalies:
        lines = [f"# ⚠️ 异常报告 — {today}", "", "## 检测到的异常", ""]
        lines.extend(anomalies)
        lines.append("")
        lines.append("> 系统仅检测异常，不修代码，不创建交易。请人工处理。")
        _write_md(ALERTS_DIR / f"{today}_ANOMALY.md", "\n".join(lines))
        log(f"⚠️ 发现 {len(anomalies)} 个异常 — 已写入 alerts/")
    else:
        log("✅ 未发现异常")


# ── 周报任务 ─────────────────────────────────────────

def run_weekly_report():
    today = date.today()
    iso_year, iso_week, _ = today.isocalendar()
    week_label = f"{iso_year}-W{iso_week:02d}"
    log(f"📅 生成周报: {week_label}")

    r = _get("/api/reports/weekly?days=7")
    narrative = r.get("narrative", "暂无复盘数据")
    total = r.get("total_amount", 0)
    plan_r = _get("/api/plan/latest?fund_code=000083")
    snapshot_r = _get("/api/snapshot/latest?fund_code=000083")
    ledger = _get("/api/pool/ledger?fund_code=000083&limit=20")

    lines = [
        f"# 周报 — {week_label}",
        f"生成时间: {datetime.now().isoformat()}",
        "",
        "## 1. 本周结论",
        narrative,
        "",
        "## 2. 数据质量",
        f"- 数据源: {snapshot_r.get('proxy_source', '?')}",
        f"- 数据日期: {snapshot_r.get('proxy_date', '?')}",
        f"- trusted: {snapshot_r.get('proxy_source','').lower() != 'mock'}",
        "",
        "## 3. MA200 偏离变化",
        f"- dev_pct: {plan_r.get('dev_pct',0)*100:.2f}%",
        f"- 估值层级: {plan_r.get('level','?')}",
        f"- 代理指数: {snapshot_r.get('proxy_close',0):.0f}",
        "",
        "## 4. risk_guard 状态",
        f"- action_allowed: {plan_r.get('action_allowed', False)}",
        f"- recommended_amount: {plan_r.get('recommended_amount')}",
        "",
        "## 5. 资金池变化",
    ]
    if isinstance(ledger, list):
        for entry in ledger[:5]:
            lines.append(f"- {entry.get('date','?')} {entry.get('entry_type','?')}: ¥{entry.get('amount',0):.2f} — {entry.get('note','')}")
    lines.append(f"- 当期总投入: ¥{total:.2f}")
    lines.append("")
    lines.append("## 6. 持仓收益变化")
    lines.append(f"- 最新净值: {snapshot_r.get('nav', 0):.4f}")
    lines.append("")
    lines.append("## 7. 实际交易 vs 系统建议")
    lines.append("（请人工填写实际执行情况）")
    lines.append("")
    lines.append("## 8. 下周观察点")
    lines.append("- 关注 MA200 趋势方向")
    lines.append("- 关注代理指数偏离度变化")
    lines.append("- 准备金余额是否充足")
    lines.append("")
    lines.append("> 本报告由 Hermes Watcher 自动生成，仅供参考。禁止输出必然上涨/稳赚/回本等预测。")

    _write_md(WEEKLY_DIR / f"{week_label}.md", "\n".join(lines))
    log(f"✅ 周报已生成: {week_label}")


# ── 警报写入工具 ─────────────────────────────────────

def _write_alerts(category: str, message: str):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    content = f"# {category}\n\n时间: {datetime.now().isoformat()}\n\n{message}\n"
    _write_md(ALERTS_DIR / f"{category}_{ts}.md", content)


# ── 心跳 ─────────────────────────────────────────────

def heartbeat_loop():
    last_hb = 0
    while running:
        now = time.time()
        if now - last_hb >= 1800:  # 30 分钟
            ts = datetime.now().strftime("%H:%M")
            next_jobs = []
            now_dt = datetime.now()
            daily_h, daily_m = map(int, DAILY_TIME.split(":"))
            next_daily = now_dt.replace(hour=daily_h, minute=daily_m, second=0)
            if next_daily <= now_dt:
                next_daily += timedelta(days=1)
            next_jobs.append(f"daily={next_daily.strftime('%m/%d %H:%M')}")

            wday = WEEKDAYS[WEEKLY_DAY]
            delta = (wday - now_dt.weekday()) % 7
            if delta == 0 and now_dt.hour * 60 + now_dt.minute >= int(WEEKLY_TIME.replace(":", "")):
                delta = 7
            next_weekly = (now_dt + timedelta(days=delta)).replace(
                hour=int(WEEKLY_TIME.split(":")[0]), minute=int(WEEKLY_TIME.split(":")[1]), second=0
            )
            next_jobs.append(f"weekly={next_weekly.strftime('%m/%d %H:%M')}")

            log(f"💓 alive. Next: {', '.join(next_jobs)}")
            last_hb = now
        time.sleep(30)


# ── 调度器 ───────────────────────────────────────────

def scheduler_loop():
    """主调度循环"""
    log("📋 调度器已启动")
    log(f"   每日采样: {DAILY_TIME}")
    log(f"   异常检查: {ANOMALY_TIME}")
    log(f"   周报: 每{WEEKLY_DAY} {WEEKLY_TIME}")

    today_done = set()
    week_done = set()

    while running:
        now = datetime.now()
        weekday = now.strftime("%a").upper()
        time_str = now.strftime("%H:%M")
        week_id = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"

        # 每日采样
        if time_str == DAILY_TIME and "daily" not in today_done:
            today_done.add("daily")
            run_daily_sample()

        # 异常检查
        if time_str == ANOMALY_TIME and "anomaly" not in today_done:
            today_done.add("anomaly")
            run_anomaly_check()

        # 周报
        if weekday == WEEKLY_DAY[:3] and time_str == WEEKLY_TIME and week_id not in week_done:
            week_done.add(week_id)
            run_weekly_report()

        # 跨天重置
        if now.strftime("%Y-%m-%d") not in str(today_done):
            today_done.clear()

        # 清理过时的周记录
        if len(week_done) > 10:
            week_done.clear()

        time.sleep(30)


# ── 信号处理 ─────────────────────────────────────────

def _shutdown(sig, frame):
    global running
    log("🛑 收到停止信号，正在退出...")
    running = False


# ── 入口 ─────────────────────────────────────────────

def main():
    global running
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print("=" * 60)
    print(" Hermes Watcher — CompoundInterestPlan 守护进程")
    print("=" * 60)
    print(f" API: {API_BASE}")
    print(f" 每日采样: {DAILY_TIME}")
    print(f" 异常检查: {ANOMALY_TIME}")
    print(f" 周报: 每{WEEKLY_DAY} {WEEKLY_TIME}")
    print(f" 自动补写: {AUTO_CATCHUP}")
    print(f" 报告目录: {REPORTS_DIR}/")
    print(f" 警报目录: {ALERTS_DIR}/")
    print("=" * 60)

    ensure_dirs()

    # 1) 健康检查
    if not check_api_health():
        log("💡 提示：Watcher 将继续运行，但任务执行需要 API 可用。")
        log("   启动 API: python -m src.app.api --port 8701")

    # 2) 检查当天采样
    check_today_sampled()

    # 3) 启动调度线程和心跳线程
    scheduler = threading.Thread(target=scheduler_loop, daemon=True, name="scheduler")
    scheduler.start()

    heartbeat = threading.Thread(target=heartbeat_loop, daemon=True, name="heartbeat")
    heartbeat.start()

    log("🚀 Hermes Watcher 运行中。按 Ctrl+C 停止。")

    try:
        while running:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    log("👋 Hermes Watcher 已停止。")


if __name__ == "__main__":
    main()
