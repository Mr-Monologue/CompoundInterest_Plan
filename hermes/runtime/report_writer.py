"""report_writer.py — Write daily/weekly reports and alerts to disk.

All reports are Markdown files. BLOCKED reports never show buy amounts.
computed_amount only appears in calculation_trace / audit sections.
"""
import json
from pathlib import Path
from datetime import date, datetime
from typing import Dict, Any


def _ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def _write(path: Path, content: str):
    _ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")
    return path


def write_daily_report(
    report_dir: Path,
    result: Dict[str, Any],
    policy: Dict[str, Any],
    today: date = None,
) -> Path:
    """Write reports/daily/YYYY-MM-DD.md. BLOCKED reports omit buy amounts."""
    if today is None:
        today = date.today()
    date_str = today.isoformat()
    status = policy["status"]
    safe = policy["safe_to_display_amount"]
    rec = policy["recommended_amount"]
    trace = result.get("calculation_trace", {}) or {}
    errors = policy.get("errors", [])

    lines = [
        f"# 每日定投报告 — {date_str}",
        f"生成时间: {datetime.now().isoformat()}",
        "",
        f"## 状态: {'✅ PASS' if status == 'PASS' else '⛔ BLOCKED'}",
        "",
        "## 概览",
        f"- 基金代码: {result.get('fund_code', '?')}",
        f"- 基金净值: {result.get('fund_nav', '?')}",
        f"- 净值日期: {result.get('fund_nav_date', '?')}",
        f"- 数据源: {result.get('data_source', '?')}",
        f"- trusted: {result.get('is_trusted', '?')}",
        f"- risk_guard: {'PASS' if result.get('risk_guard_passed') else 'FAIL'}",
        f"- action_allowed: {result.get('action_allowed')}",
        "",
    ]

    if safe:
        lines.append(f"## 建议金额: ¥{rec:.2f}（仅供人工复核）")
        lines.append("")
    else:
        lines.append("## 建议金额: null（BLOCKED）")
        lines.append("")
        if errors:
            lines.append("## 阻断原因")
            for e in errors:
                lines.append(f"- {e}")
            lines.append("")

    lines.append("## 审计详情 (calculation_trace)")
    lines.append("| 字段 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| computed_amount | ¥{trace.get('computed_amount', 0):.2f} |")
    lines.append(f"| fixed_amount | ¥{trace.get('fixed_amount', 0):.2f} |")
    lines.append(f"| dynamic_amount | ¥{trace.get('dynamic_amount', 0):.2f} |")
    lines.append(f"| reserve_before | ¥{trace.get('reserve_before', 0):.2f} |")
    lines.append(f"| reserve_after | ¥{trace.get('reserve_after', 0):.2f} |")
    lines.append("")
    lines.append("> ⚠️ computed_amount 仅供审计，不得作为建议金额。")
    lines.append("")
    lines.append("> 本报告由 Hermes Runtime 自动生成。不构成投资建议。")

    return _write(report_dir / "daily" / f"{date_str}.md", "\n".join(lines))


def write_blocked_alert(
    alert_dir: Path,
    result: Dict[str, Any],
    policy: Dict[str, Any],
    today: date = None,
) -> Path:
    """Write alerts/YYYY-MM-DD_BLOCKED.md. Must NOT show buy amounts."""
    if today is None:
        today = date.today()
    date_str = today.isoformat()
    errors = policy.get("errors", [])

    lines = [
        f"# ⛔ BLOCKED — {date_str}",
        "",
        f"生成时间: {datetime.now().isoformat()}",
        "",
        "## 阻断原因",
    ]
    for e in errors:
        lines.append(f"- {e}")
    lines.append("")
    lines.append("## 数据摘要")
    lines.append(f"- 基金代码: {result.get('fund_code', '?')}")
    lines.append(f"- 数据源: {result.get('data_source', '?')}")
    lines.append(f"- trusted: {result.get('is_trusted', '?')}")
    lines.append(f"- risk_guard: {'PASS' if result.get('risk_guard_passed') else 'FAIL'}")
    lines.append(f"- action_allowed: {result.get('action_allowed')}")
    lines.append(f"- 建议金额: null")
    lines.append("")
    lines.append("> ⛔ 本次不输出买入金额。请人工复核。")

    return _write(alert_dir / f"{date_str}_BLOCKED.md", "\n".join(lines))


def write_anomaly_alert(
    alert_dir: Path,
    anomalies: list,
    today: date = None,
) -> Path:
    """Write alerts/YYYY-MM-DD_ANOMALY.md."""
    if today is None:
        today = date.today()
    date_str = today.isoformat()

    lines = [
        f"# ⚠️ 异常报告 — {date_str}",
        f"生成时间: {datetime.now().isoformat()}",
        "",
        "## 检测到的异常",
    ]
    for a in anomalies:
        lines.append(f"- {a}")
    lines.append("")
    lines.append("> 系统仅检测异常，不修代码，不创建交易。请人工处理。")

    return _write(alert_dir / f"{date_str}_ANOMALY.md", "\n".join(lines))


def write_weekly_report(
    report_dir: Path,
    data: Dict[str, Any],
    week_label: str = None,
) -> Path:
    """Write reports/weekly/YYYY-WW.md."""
    if week_label is None:
        today = date.today()
        iso = today.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"

    lines = [
        f"# 周报 — {week_label}",
        f"生成时间: {datetime.now().isoformat()}",
        "",
        "## 本周结论",
        data.get("narrative", "暂无结论"),
        "",
        "## 数据摘要",
        f"- 期间总投入: ¥{data.get('total_amount', 0):.2f}",
        f"- 记录数: {data.get('record_count', 0)}",
        "",
        "> 本报告由 Hermes Runtime 自动生成，不构成投资建议。",
    ]

    return _write(report_dir / "weekly" / f"{week_label}.md", "\n".join(lines))
