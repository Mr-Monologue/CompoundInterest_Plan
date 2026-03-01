#!/bin/bash
# SmartInvest 启动脚本 — 适配 RK3588 / clawbot
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 激活虚拟环境（如存在）
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

# 禁用代理（国内数据源直连）
export http_proxy=""
export https_proxy=""
export HTTP_PROXY=""
export HTTPS_PROXY=""
export NO_PROXY="*"

echo "========================================="
echo "  SmartInvest v2.0 — 智能定投系统"
echo "  部署目标: RK3588 / clawbot"
echo "========================================="

cd backend
exec python -m uvicorn main:app --host 0.0.0.0 --port 8000
