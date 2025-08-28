#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块
- 默认参数定义
- 用户自定义JSON读取
- 配置验证
"""

import os
import json
import json
from pathlib import Path
from dotenv import load_dotenv
from typing import Dict, Any, Optional

# 加载 .env 文件
load_dotenv()

CONFIG_FILE = Path("data/config.json")

# 默认配置
DEFAULT_CONFIG = {
    "fund_code": "000083",
    "fund_name": "汇添富消费行业混合",
    "fund_name_en": "000083.SZ",  # yfinance代码
    "proxy_index": "000932",  # 估值代理指数
    # 数据源配置
    "data_sources": {
        "primary": "akshare",  # akshare, yfinance, ttfund
        "fallback": "yfinance",
        "cache_ttl": 900,  # 15分钟缓存
    },
    # 动态定投参数
    "weekly_budget": 200.0,
    "fixed_ratio": 0.40,
    "reserve_cap_months": 3,
    "max_weekly_multiple": 3.0,
    # 估值分层阈值（按 MA200 偏离）
    "ma200_low": -10.0,  # ≤ -10% → 低估
    "ma200_mid": 5.0,  # (-10%, 5%] → 合理；>5% → 偏高
    # 低/中/高估对应动用准备金比例
    "alloc_low": 0.75,
    "alloc_mid": 0.25,
    "alloc_high": 0.0,
    # 持仓配置
    "manual_holdings": {
        "enabled": True,
        "units_left": 6.63,
        "avg_cost": 6.8627,
        "realized_pnl": -7.24,
    },
    # 文件路径
    "files": {
        "state": "state.json",
        "dca_log": "dca_log.csv",
        "charts": {"ma200": "chart_ma200.png", "buypoints": "chart_buypoints.png"},
    },
}


def load_config():
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"配置文件 {CONFIG_FILE} 未找到")

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 从环境变量覆盖配置
    config["http_proxy"] = os.getenv("HTTP_PROXY", config.get("http_proxy", ""))
    config["timeout"] = int(os.getenv("TIMEOUT", config.get("timeout", 10)))
    config["user_agent"] = os.getenv(
        "USER_AGENT", config.get("user_agent", "Mozilla/5.0")
    )

    print(f"数据源路径: {CONFIG_FILE}")
    print(f"数据源版本: {config.get('version', '未知')}")
    return config


def load_all_funds_config():
    cfg = load_config()
    defaults = cfg.get("defaults", {})
    funds = []
    for f in cfg.get("funds", []):
        merged = _deep_merge(defaults, f)
        merged["fund_code"] = f["fund_code"]
        funds.append(merged)
    return funds, cfg


def _deep_merge(base: Dict, update: Dict) -> Dict:
    """递归合并字典"""
    result = base.copy()

    for key, value in update.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def save_config(config: Dict[str, Any], config_path: str = "data/config.json") -> bool:
    """
    保存配置到文件

    Args:
        config: 配置字典
        config_path: 配置文件路径

    Returns:
        是否保存成功
    """
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        print(f"✓ 配置已保存到: {config_path}")
        return True
    except Exception as e:
        print(f"✗ 配置保存失败: {e}")
        return False


def validate_config(config: Dict[str, Any]) -> tuple[bool, list[str]]:
    """
    验证配置参数的有效性

    Args:
        config: 配置字典

    Returns:
        (是否有效, 错误信息列表)
    """
    errors = []

    # 验证数值参数
    if config["weekly_budget"] < 0:
        errors.append("周预算必须 ≥ 0")

    if not (0 <= config["fixed_ratio"] <= 1):
        errors.append("固定比例必须在 [0, 1] 范围内")

    if config["max_weekly_multiple"] < 1:
        errors.append("最大周乘数必须 ≥ 1")

    if config["alloc_low"] < 0 or config["alloc_mid"] < 0 or config["alloc_high"] < 0:
        errors.append("分配比例不能为负数")

    # 验证阈值逻辑
    if config["ma200_low"] >= config["ma200_mid"]:
        errors.append("MA200低阈值必须小于中阈值")

    return len(errors) == 0, errors


def get_fund_info(config: Dict[str, Any]) -> Dict[str, str]:
    """获取基金基本信息"""
    return {
        "code": config["fund_code"],
        "name": config["fund_name"],
        "name_en": config["fund_name_en"],
        "proxy_index": config["proxy_index"],
    }


if __name__ == "__main__":
    # 测试配置加载
    config = load_config()
    is_valid, errors = validate_config(config)

    if is_valid:
        print("✓ 配置验证通过")
        print(f"基金: {config['fund_name']} ({config['fund_code']})")
        print(f"周预算: {config['weekly_budget']}")
    else:
        print("✗ 配置验证失败:")
        for error in errors:
            print(f"  - {error}")
